/***************************************************************************//**
 *   @file   no_os_gpio.c
 *   @brief  Implementation of the GPIO Interface
 *   @author Antoniu Miclaus (antoniu.miclaus@analog.com)
********************************************************************************
 * Copyright 2020(c) Analog Devices, Inc.
 *
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *  - Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 *  - Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in
 *    the documentation and/or other materials provided with the
 *    distribution.
 *  - Neither the name of Analog Devices, Inc. nor the names of its
 *    contributors may be used to endorse or promote products derived
 *    from this software without specific prior written permission.
 *  - The use of this software may or may not infringe the patent rights
 *    of one or more patent holders.  This license does not release you
 *    from the requirement that you obtain separate licenses from these
 *    patent holders to use this software.
 *  - Use of the software either in source or binary form, must be run
 *    on or directly connected to an Analog Devices Inc. component.
 *
 * THIS SOFTWARE IS PROVIDED BY ANALOG DEVICES "AS IS" AND ANY EXPRESS OR
 * IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, NON-INFRINGEMENT,
 * MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
 * IN NO EVENT SHALL ANALOG DEVICES BE LIABLE FOR ANY DIRECT, INDIRECT,
 * INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 * LIMITED TO, INTELLECTUAL PROPERTY RIGHTS, PROCUREMENT OF SUBSTITUTE GOODS OR
 * SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
 * CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
 * OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
*******************************************************************************/

#include <inttypes.h>
#include "no_os_gpio.h"
#include <stdlib.h>
#include "no_os_error.h"
#ifdef FREERTOS_INTEGRATION
#include "FreeRTOS.h"
#include "semphr.h"
#include "task.h"

static int32_t no_os_gpio_create_mutex(struct no_os_gpio_desc *desc)
{
	desc->mutex = xSemaphoreCreateMutex();

	return desc->mutex ? 0 : -1;
}

static void no_os_gpio_lock(struct no_os_gpio_desc *desc)
{
	if (desc && desc->mutex &&
	    (xTaskGetSchedulerState() == taskSCHEDULER_RUNNING))
		xSemaphoreTake((SemaphoreHandle_t)desc->mutex, portMAX_DELAY);
}

static void no_os_gpio_unlock(struct no_os_gpio_desc *desc)
{
	if (desc && desc->mutex &&
	    (xTaskGetSchedulerState() == taskSCHEDULER_RUNNING))
		xSemaphoreGive((SemaphoreHandle_t)desc->mutex);
}
#else
static int32_t no_os_gpio_create_mutex(struct no_os_gpio_desc *desc)
{
	(void)desc;
	return 0;
}

static void no_os_gpio_lock(struct no_os_gpio_desc *desc)
{
	(void)desc;
}

static void no_os_gpio_unlock(struct no_os_gpio_desc *desc)
{
	(void)desc;
}
#endif

/******************************************************************************/
/************************ Functions Definitions *******************************/
/******************************************************************************/

/**
 * @brief Obtain the GPIO decriptor.
 * @param desc - The GPIO descriptor.
 * @param param - GPIO Initialization parameters.
 * @return 0 in case of success, -1 otherwise.
 */
int32_t no_os_gpio_get(struct no_os_gpio_desc **desc,
		       const struct no_os_gpio_init_param *param)
{
	if (!param)
		return -1;

	if ((param->platform_ops->gpio_ops_get(desc, param)))
		return -1;

	(*desc)->platform_ops = param->platform_ops;

	if (no_os_gpio_create_mutex(*desc) < 0) {
		(*desc)->platform_ops->gpio_ops_remove(*desc);
		*desc = NULL;
		return -1;
	}

	return 0;
}

/**
 * @brief Get the value of an optional GPIO.
 * @param desc - The GPIO descriptor.
 * @param param - GPIO Initialization parameters.
 * @return 0 in case of success, -1 otherwise.
 */
int32_t no_os_gpio_get_optional(struct no_os_gpio_desc **desc,
				const struct no_os_gpio_init_param *param)
{
	if (!param || (param->number == -1)) {
		*desc = NULL;
		return 0;
	}

	if ((param->platform_ops->gpio_ops_get_optional(desc, param)))
		return -1;

	(*desc)->platform_ops = param->platform_ops;

	if (no_os_gpio_create_mutex(*desc) < 0) {
		(*desc)->platform_ops->gpio_ops_remove(*desc);
		*desc = NULL;
		return -1;
	}

	return 0;
}
/**
 * @brief Free the resources allocated by no_os_gpio_get().
 * @param desc - The GPIO descriptor.
 * @return 0 in case of success, -1 otherwise.
 */
int32_t no_os_gpio_remove(struct no_os_gpio_desc *desc)
{
	if (desc) {
#ifdef FREERTOS_INTEGRATION
		SemaphoreHandle_t mutex = (SemaphoreHandle_t)desc->mutex;

		desc->mutex = NULL;
		if (mutex)
			vSemaphoreDelete(mutex);
#endif
		return desc->platform_ops->gpio_ops_remove(desc);
	}

	return 0;
}

/**
 * @brief Enable the input direction of the specified GPIO.
 * @param desc - The GPIO descriptor.
 * @return 0 in case of success, -1 otherwise.
 */
int32_t no_os_gpio_direction_input(struct no_os_gpio_desc *desc)
{
	int32_t ret = 0;

	if (desc) {
		no_os_gpio_lock(desc);
		ret = desc->platform_ops->gpio_ops_direction_input(desc);
		no_os_gpio_unlock(desc);
	}

	return ret;
}

/**
 * @brief Enable the output direction of the specified GPIO.
 * @param desc - The GPIO descriptor.
 * @param value - The value.
 *                Example: NO_OS_GPIO_HIGH
 *                         NO_OS_GPIO_LOW
 * @return 0 in case of success, -1 otherwise.
 */
int32_t no_os_gpio_direction_output(struct no_os_gpio_desc *desc,
				    uint8_t value)
{
	int32_t ret = 0;

	if (desc) {
		no_os_gpio_lock(desc);
		ret = desc->platform_ops->gpio_ops_direction_output(desc, value);
		no_os_gpio_unlock(desc);
	}

	return ret;
}

/**
 * @brief Get the direction of the specified GPIO.
 * @param desc - The GPIO descriptor.
 * @param direction - The direction.
 *                    Example: NO_OS_GPIO_OUT
 *                             NO_OS_GPIO_IN
 * @return 0 in case of success, -1 otherwise.
 */
int32_t no_os_gpio_get_direction(struct no_os_gpio_desc *desc,
				 uint8_t *direction)
{
	int32_t ret = 0;

	if (desc) {
		no_os_gpio_lock(desc);
		ret = desc->platform_ops->gpio_ops_get_direction(desc, direction);
		no_os_gpio_unlock(desc);
	}

	return ret;
}

/**
 * @brief Set the value of the specified GPIO.
 * @param desc - The GPIO descriptor.
 * @param value - The value.
 *                Example: NO_OS_GPIO_HIGH
 *                         NO_OS_GPIO_LOW
 * @return 0 in case of success, -1 otherwise.
 */
int32_t no_os_gpio_set_value(struct no_os_gpio_desc *desc,
			     uint8_t value)
{
	int32_t ret = 0;

	if (desc) {
		no_os_gpio_lock(desc);
		ret = desc->platform_ops->gpio_ops_set_value(desc, value);
		no_os_gpio_unlock(desc);
	}

	return ret;
}

/**
 * @brief Get the value of the specified GPIO.
 * @param desc - The GPIO descriptor.
 * @param value - The value.
 *                Example: NO_OS_GPIO_HIGH
 *                         NO_OS_GPIO_LOW
 * @return 0 in case of success, -1 otherwise.
 */
int32_t no_os_gpio_get_value(struct no_os_gpio_desc *desc,
			     uint8_t *value)
{
	int32_t ret = 0;

	if (desc) {
		no_os_gpio_lock(desc);
		ret = desc->platform_ops->gpio_ops_get_value(desc, value);
		no_os_gpio_unlock(desc);
	}

	return ret;
}
